import { render, screen, within } from '@testing-library/react'
import { describe, it, expect, afterEach, vi } from 'vitest'
import React from 'react'
import { CommoditySpecificationForm, CommoditySchemaVersion } from '@/components/commodity/commodity-specification-form'
import { cleanup } from '@testing-library/react'
import { components } from "@/lib/api/generated/schema"

// Fix for radix-ui pointer capture in jsdom
if (typeof window !== 'undefined' && typeof window.HTMLElement !== 'undefined') {
  window.HTMLElement.prototype.hasPointerCapture = vi.fn().mockReturnValue(false)
  window.HTMLElement.prototype.releasePointerCapture = vi.fn()
  window.HTMLElement.prototype.setPointerCapture = vi.fn()
}

afterEach(() => {
  cleanup()
})

describe('CommoditySpecificationForm - Rendering and Metadata', () => {
  const mockSchema: CommoditySchemaVersion = {
    id: 'test-schema-id',
    version: 1,
    commodity_id: 'test-commodity',
    status: 'published',
    attributes: [
      {
        id: '1',
        key: 'grade',
        label_en: 'Grade',
        label_fa: 'گرید',
        data_type: 'enum',
        is_required: true,
        sort_order: 1,
        display_group: 'Quality',
        enum_metadata: {
          options: [
            { canonical_value: 'a', label_en: 'Type A', label_fa: 'نوع آ', sort_order: 2 },
            { canonical_value: 'b', label_en: 'Type B', label_fa: 'نوع ب', sort_order: 1 }
          ]
        }
      },
      {
        id: '2',
        key: 'viscosity',
        label_en: 'Viscosity',
        label_fa: 'گرانروی',
        data_type: 'number',
        is_required: false,
        sort_order: 2,
        display_group: 'Quality',
        unit_metadata: { canonical_unit: 'cSt' },
        validation_metadata: { min: 10, max: 100 }
      },
      {
        id: '3',
        key: 'active',
        label_en: 'Active',
        label_fa: 'فعال',
        data_type: 'boolean',
        is_required: false,
        sort_order: 3
      },
      {
        id: '4',
        key: 'notes',
        label_en: 'Notes',
        label_fa: 'یادداشت',
        data_type: 'string',
        is_required: false,
        sort_order: 4,
        validation_metadata: { min_length: 5, max_length: 255 }
      },
      {
        id: '5',
        key: 'count',
        label_en: 'Count',
        label_fa: 'تعداد',
        data_type: 'integer',
        is_required: true,
        sort_order: 5,
        validation_metadata: { min: 0 }
      }
    ]
  }

  it('renders correctly in Persian (default) with groups', () => {
    render(<CommoditySpecificationForm schema={mockSchema} value={{}} onChange={() => {}} />)

    expect(screen.getByText('Quality')).toBeInTheDocument()
    expect(screen.getByText('گرید')).toBeInTheDocument()
    expect(screen.getByText('گرانروی')).toBeInTheDocument()
    expect(screen.getByText('فعال')).toBeInTheDocument()
    expect(screen.getByText('یادداشت')).toBeInTheDocument()
    expect(screen.getByText('تعداد')).toBeInTheDocument()

    const gradeLabel = screen.getByText('گرید').closest('label')
    expect(within(gradeLabel!).getByText('*')).toBeInTheDocument()

    const countLabel = screen.getByText('تعداد').closest('label')
    expect(within(countLabel!).getByText('*')).toBeInTheDocument()

    const viscosityLabel = screen.getByText('گرانروی').closest('label')
    expect(within(viscosityLabel!).getByText('(cSt)')).toBeInTheDocument()
  })

  it('renders correctly in English with validation attributes applied', () => {
    render(<CommoditySpecificationForm schema={mockSchema} value={{}} onChange={() => {}} locale="en" />)

    expect(screen.getByText('Quality')).toBeInTheDocument()
    expect(screen.getByText('Grade')).toBeInTheDocument()
    expect(screen.getByText('Viscosity')).toBeInTheDocument()
    expect(screen.getByText('Active')).toBeInTheDocument()
    expect(screen.getByText('Notes')).toBeInTheDocument()
    expect(screen.getByText('Count')).toBeInTheDocument()

    const notesInput = screen.getByRole('textbox', { name: /Notes/i })
    expect(notesInput).toHaveAttribute('minLength', '5')
    expect(notesInput).toHaveAttribute('maxLength', '255')

    const viscosityInput = screen.getByRole('spinbutton', { name: /Viscosity/i })
    expect(viscosityInput).toHaveAttribute('min', '10')
    expect(viscosityInput).toHaveAttribute('max', '100')

    const countInput = screen.getByRole('spinbutton', { name: /Count/i })
    expect(countInput).toHaveAttribute('min', '0')
  })
})

describe('CommoditySpecificationForm - Interaction', () => {
  const mockSchema: CommoditySchemaVersion = {
    id: 'test-schema-id',
    version: 1,
    commodity_id: 'test-commodity',
    status: 'published',
    attributes: [
      { id: '1', key: 'grade', label_en: 'Grade', label_fa: 'گرید', data_type: 'enum', enum_metadata: { options: [{ canonical_value: 'a', label_en: 'Type A', label_fa: 'نوع آ' }] } },
      { id: '2', key: 'viscosity', label_en: 'Viscosity', label_fa: 'گرانروی', data_type: 'number' },
      { id: '3', key: 'active', label_en: 'Active', label_fa: 'فعال', data_type: 'boolean' },
      { id: '4', key: 'notes', label_en: 'Notes', label_fa: 'یادداشت', data_type: 'string' },
      { id: '5', key: 'count', label_en: 'Count', label_fa: 'تعداد', data_type: 'integer' },
      { id: '6', key: 'bad_type', label_en: 'Bad Type', label_fa: 'نوع بد', data_type: 'unknown_type' as components["schemas"]["DataTypeEnum"] }
    ]
  }

  function StatefulHarness({ schema = mockSchema }: { schema?: CommoditySchemaVersion }) {
    const [value, setValue] = React.useState<Record<string, unknown>>({})
    return <CommoditySpecificationForm schema={schema} value={value} onChange={setValue} locale="en" />
  }

  it('handles string updates correctly', async () => {
    const user = (await import('@testing-library/user-event')).default.setup()
    render(<StatefulHarness />)

    const input = screen.getByRole('textbox', { name: /Notes/i })
    await user.type(input, 'Hello World')
    expect(input).toHaveValue('Hello World')
  })

  it('handles boolean toggles correctly', async () => {
    const user = (await import('@testing-library/user-event')).default.setup()
    render(<StatefulHarness />)

    const toggle = screen.getByRole('switch', { name: /Active/i })
    expect(toggle).not.toBeChecked()

    await user.click(toggle)
    expect(toggle).toBeChecked()
  })

  it('handles number and integer parsing and emits correct numeric values', async () => {
    const user = (await import('@testing-library/user-event')).default.setup()
    let lastValue = {}

    function NumericHarness() {
      const [value, setValue] = React.useState<Record<string, unknown>>({})
      lastValue = value
      return <CommoditySpecificationForm schema={mockSchema} value={value} onChange={setValue} locale="en" />
    }

    render(<NumericHarness />)

    const numberInput = screen.getByRole("spinbutton", { name: /Viscosity/i })
    await user.clear(numberInput)
    await user.type(numberInput, '12.5')

    expect(numberInput).toHaveValue(12.5)
    expect(lastValue).toMatchObject({ viscosity: 12.5 })

    const integerInput = screen.getByRole("spinbutton", { name: /Count/i })
    await user.clear(integerInput)
    await user.type(integerInput, '15')

    expect(integerInput).toHaveValue(15)
    expect(lastValue).toMatchObject({ count: 15 })

    // Test decimal handling for integers
    await user.clear(integerInput)
    await user.type(integerInput, '15.9')

    // JS Number field with step 1 allows typing decimals in some browsers, but our JS parse drops them to Int
    expect(lastValue).toMatchObject({ count: 15 })

    // Test empty value handling
    await user.clear(numberInput)
    expect(numberInput).toHaveValue(null)
    expect(lastValue).toMatchObject({ viscosity: undefined })
  })

  it('renders generic failure message for unsupported type safely', () => {
    render(<StatefulHarness />)
    expect(screen.getByText('Unsupported field type: unknown_type')).toBeInTheDocument()
  })

  it('handles enum select correctly', async () => {
    const user = (await import('@testing-library/user-event')).default.setup()
    let lastValue = {}

    function EnumHarness() {
      const [value, setValue] = React.useState<Record<string, unknown>>({})
      lastValue = value
      return <CommoditySpecificationForm schema={mockSchema} value={value} onChange={setValue} locale="en" />
    }

    render(<EnumHarness />)

    const trigger = screen.getByRole('combobox', { name: /Grade/i })
    await user.click(trigger)

    const option = await screen.findByRole('option', { name: 'Type A' })
    await user.click(option)

    expect(lastValue).toMatchObject({ grade: 'a' })
  })
})

describe('CommoditySpecificationForm - Genericity Proof', () => {
  function StatefulHarness({ schema }: { schema: CommoditySchemaVersion }) {
    const [value, setValue] = React.useState<Record<string, unknown>>({})
    return <CommoditySpecificationForm schema={schema} value={value} onChange={setValue} locale="en" />
  }

  it('can render Bitumen and Base Oil schemas through the exact same component', () => {
    const bitumenSchema: CommoditySchemaVersion = {
      id: 'bitumen', version: 1, commodity_id: 'bitumen', status: 'published',
      attributes: [
        { id: '1', key: 'penetration', label_en: 'Penetration Grade', label_fa: 'درجه نفوذ', data_type: 'string' }
      ]
    }
    const baseOilSchema: CommoditySchemaVersion = {
      id: 'base-oil', version: 1, commodity_id: 'base-oil', status: 'published',
      attributes: [
        { id: '2', key: 'viscosity_grade', label_en: 'Viscosity Grade', label_fa: 'گرید گرانروی', data_type: 'enum', enum_metadata: { options: [{ canonical_value: 'sn500', label_en: 'SN500', label_fa: 'SN500' }] } }
      ]
    }

    const { unmount } = render(<StatefulHarness schema={bitumenSchema} />)
    expect(screen.getByRole('textbox', { name: /Penetration Grade/i })).toBeInTheDocument()

    unmount()
    render(<StatefulHarness schema={baseOilSchema} />)
    expect(screen.getByText(/Viscosity Grade/i)).toBeInTheDocument()
  })
})
