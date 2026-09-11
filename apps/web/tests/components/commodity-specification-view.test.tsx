import React from 'react'
import { CommoditySpecificationView, CommoditySchemaVersion } from '@/components/commodity/commodity-specification-view'
import { CommoditySpecificationForm } from '@/components/commodity/commodity-specification-form'
import { render, screen, cleanup, within } from '@testing-library/react'
import { afterEach, describe, it, expect, vi } from 'vitest'

// Fix for radix-ui pointer capture in jsdom (needed for Form interaction tests, kept for consistency)
if (typeof window !== 'undefined' && typeof window.HTMLElement !== 'undefined') {
  window.HTMLElement.prototype.hasPointerCapture = vi.fn().mockReturnValue(false)
  window.HTMLElement.prototype.releasePointerCapture = vi.fn()
  window.HTMLElement.prototype.setPointerCapture = vi.fn()
}

afterEach(() => {
  cleanup()
})

describe('CommoditySpecificationView - Rendering and Metadata', () => {
  const mockSchema: CommoditySchemaVersion = {
    id: 'test-schema-id',
    version: 1,
    commodity_id: 'test-commodity',
    status: 'published',
    attributes: [
      {
        ...{ unit_metadata: {}, enum_metadata: {}, validation_metadata: {} }, id: '1',
        key: 'grade',
        label_en: 'Grade',
        label_fa: 'گرید',
        data_type: 'enum',
        is_required: true,
        sort_order: 1,
        display_group: 'Quality',
        enum_metadata: {
          options: [
            { value: 'a', label_en: 'Type A', label_fa: 'نوع آ', sort_order: 2 },
            { value: 'b', label_en: 'Type B', label_fa: 'نوع ب', sort_order: 1 }
          ]
        }
      },
      {
        ...{ unit_metadata: {}, enum_metadata: {}, validation_metadata: {} }, id: '2',
        key: 'viscosity',
        label_en: 'Viscosity',
        label_fa: 'گرانروی',
        data_type: 'number',
        is_required: false,
        sort_order: 2,
        display_group: 'Quality',
        unit_metadata: { canonical_unit: 'cSt' },
        validation_metadata: { minimum: 10, maximum: 100 }
      },
      {
        ...{ unit_metadata: {}, enum_metadata: {}, validation_metadata: {} }, id: '3',
        key: 'active',
        label_en: 'Active',
        label_fa: 'فعال',
        data_type: 'boolean',
        is_required: false,
        sort_order: 3
      },
      {
        ...{ unit_metadata: {}, enum_metadata: {}, validation_metadata: {} }, id: '4',
        key: 'notes',
        label_en: 'Notes',
        label_fa: 'یادداشت',
        data_type: 'string',
        is_required: false,
        sort_order: 4,
        validation_metadata: { minLength: 5, maxLength: 255 }
      },
      {
        ...{ unit_metadata: {}, enum_metadata: {}, validation_metadata: {} }, id: '5',
        key: 'count',
        label_en: 'Count',
        label_fa: 'تعداد',
        data_type: 'integer',
        is_required: true,
        sort_order: 5,
        validation_metadata: { minimum: 0 }
      },
      {
        ...{ unit_metadata: {}, enum_metadata: {}, validation_metadata: {} }, id: '6',
        key: 'missing_optional',
        label_en: 'Missing',
        label_fa: 'خالی',
        data_type: 'string',
        is_required: false,
        sort_order: 6
      }
    ]
  }

  const mockValue = {
    grade: 'a',
    viscosity: 12.5,
    active: true,
    notes: 'Hello',
    count: 15
    // missing_optional is undefined
  }

  it('renders correctly in Persian (default) with groups and labels', () => {
    render(<CommoditySpecificationView schema={mockSchema} value={mockValue} />)

    expect(screen.getByText('Quality')).toBeInTheDocument()

    // Labels
    expect(screen.getByText('گرید')).toBeInTheDocument()
    expect(screen.getByText('گرانروی')).toBeInTheDocument()
    expect(screen.getByText('فعال')).toBeInTheDocument()
    expect(screen.getByText('یادداشت')).toBeInTheDocument()
    expect(screen.getByText('تعداد')).toBeInTheDocument()

    // Values
    expect(screen.getByText('نوع آ')).toBeInTheDocument() // Enum resolved to FA
    expect(screen.getByText('12.5')).toBeInTheDocument()
    expect(screen.getByText('بله')).toBeInTheDocument() // Boolean true resolved to FA
    expect(screen.getByText('Hello')).toBeInTheDocument()
    expect(screen.getByText('15')).toBeInTheDocument()
    expect(screen.getByText('—')).toBeInTheDocument() // Missing optional

    // Unit
    const viscosityTerm = screen.getByText('گرانروی').closest('dt')
    expect(within(viscosityTerm!).getByText('(cSt)')).toBeInTheDocument()
  })

  it('renders correctly in English', () => {
    render(<CommoditySpecificationView schema={mockSchema} value={mockValue} locale="en" />)

    expect(screen.getByText('Quality')).toBeInTheDocument()
    expect(screen.getByText('Grade')).toBeInTheDocument()

    // Enum resolved to EN
    expect(screen.getByText('Type A')).toBeInTheDocument()
    // Boolean true resolved to EN
    expect(screen.getByText('Yes')).toBeInTheDocument()
  })
})

describe('CommoditySpecificationView - Historical Rendering Stability', () => {
  const v1Schema: CommoditySchemaVersion = {
    id: 'schema-v1', version: 1, commodity_id: 'test', status: 'published',
    attributes: [
      { ...{ unit_metadata: {}, enum_metadata: {}, validation_metadata: {} }, id: '1', key: 'grade', label_en: 'Grade', label_fa: 'گرید', data_type: 'enum', sort_order: 1, enum_metadata: { options: [{ value: 'old_a', label_en: 'Old Type A', label_fa: 'نوع آ قدیم' }] } }
    ]
  }

  const v2Schema: CommoditySchemaVersion = {
    id: 'schema-v2', version: 2, commodity_id: 'test', status: 'published',
    attributes: [
      { ...{ unit_metadata: {}, enum_metadata: {}, validation_metadata: {} }, id: '1', key: 'grade', label_en: 'Grade', label_fa: 'گرید', data_type: 'enum', sort_order: 1, enum_metadata: { options: [{ value: 'old_a', label_en: 'New Type A', label_fa: 'نوع آ جدید' }] } }
    ]
  }

  it('proves v1 schema renders with v1 semantics and v2 schema renders with v2 semantics for the same value', () => {
    const value = { grade: 'old_a' }

    const { unmount } = render(<CommoditySpecificationView schema={v1Schema} value={value} locale="en" />)
    expect(screen.getByText('Old Type A')).toBeInTheDocument()
    unmount()

    render(<CommoditySpecificationView schema={v2Schema} value={value} locale="en" />)
    expect(screen.getByText('New Type A')).toBeInTheDocument()
  })
})

describe('CommoditySpecificationView - Epic Integration Form to View Flow', () => {
  const bitumenSchema: CommoditySchemaVersion = {
    id: 'bitumen', version: 1, commodity_id: 'bitumen', status: 'published',
    attributes: [
      { ...{ unit_metadata: {}, enum_metadata: {}, validation_metadata: {} }, id: '1', key: 'penetration', label_en: 'Penetration Grade', label_fa: 'درجه نفوذ', data_type: 'string', sort_order: 1 }
    ]
  }

  const baseOilSchema: CommoditySchemaVersion = {
    id: 'base-oil', version: 1, commodity_id: 'base-oil', status: 'published',
    attributes: [
      { ...{ unit_metadata: {}, enum_metadata: {}, validation_metadata: {} }, id: '2', key: 'viscosity_grade', label_en: 'Viscosity Grade', label_fa: 'گرید گرانروی', data_type: 'enum', sort_order: 1, enum_metadata: { options: [{ value: 'sn500', label_en: 'SN500', label_fa: 'SN500' }] } }
    ]
  }

  function StatefulFlowHarness({ schema }: { schema: CommoditySchemaVersion }) {
    const [value, setValue] = React.useState<Record<string, unknown>>({})
    return (
      <div>
        <div data-testid="form-container">
          <CommoditySpecificationForm schema={schema} value={value} onChange={setValue} locale="en" />
        </div>
        <div data-testid="view-container">
          <CommoditySpecificationView schema={schema} value={value} locale="en" />
        </div>
      </div>
    )
  }

  it('can run Form -> View flow for Bitumen', async () => {
    const user = (await import('@testing-library/user-event')).default.setup()
    render(<StatefulFlowHarness schema={bitumenSchema} />)

    const input = screen.getByRole('textbox', { name: /Penetration Grade/i })
    await user.type(input, '60/70')

    const viewContainer = screen.getByTestId('view-container')
    expect(within(viewContainer).getByText('60/70')).toBeInTheDocument()
  })

  it('can run Form -> View flow for Base Oil using the exact same components', async () => {
    const user = (await import('@testing-library/user-event')).default.setup()
    render(<StatefulFlowHarness schema={baseOilSchema} />)

    const trigger = screen.getByRole('combobox', { name: /Viscosity Grade/i })
    await user.click(trigger)

    const option = await screen.findByRole('option', { name: 'SN500' })
    await user.click(option)

    const viewContainer = screen.getByTestId('view-container')
    expect(within(viewContainer).getByText('SN500')).toBeInTheDocument()
  })
})
